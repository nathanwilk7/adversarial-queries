SET join_collapse_limit = 1;
SELECT count(*)
FROM ((movie_link CROSS JOIN (title CROSS JOIN name)) CROSS JOIN cast_info) CROSS JOIN link_type
WHERE name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
