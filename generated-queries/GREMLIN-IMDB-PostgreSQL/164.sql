SELECT count(*)
FROM aka_title, cast_info, kind_type, link_type, movie_link, name, title
WHERE kind_type.kind = 'movie'
  AND name.name_pcode_nf = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
