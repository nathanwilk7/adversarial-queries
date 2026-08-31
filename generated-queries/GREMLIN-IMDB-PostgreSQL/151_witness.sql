SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((movie_link CROSS JOIN (title CROSS JOIN aka_title)) CROSS JOIN link_type) CROSS JOIN info_type) CROSS JOIN name) CROSS JOIN movie_info) CROSS JOIN person_info
WHERE aka_title.title = 'Anonima ricatti'
  AND aka_title.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
