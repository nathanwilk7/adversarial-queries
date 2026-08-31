SET join_collapse_limit = 1;
SELECT count(*)
FROM (((aka_name CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN name) CROSS JOIN cast_info
WHERE name.surname_pcode = ''
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
